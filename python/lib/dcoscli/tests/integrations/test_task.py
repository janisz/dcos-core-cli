import collections
import json
import os
import re
import subprocess
import sys
import time

import pytest

import dcos.util as util
from dcos.util import create_schema

from dcoscli.test.common import (assert_command, assert_lines,
                                 assert_lines_range, exec_command,
                                 popen_tty)
from dcoscli.test.marathon import (add_app, app, remove_app,
                                   watch_all_deployments)
from ..fixtures.task import task_fixture

if not util.is_windows_platform():
    import termios
    import tty

SLEEP_COMPLETED = 'tests/data/marathon/apps/sleep-completed.json'
SLEEP_COMPLETED1 = 'tests/data/marathon/apps/sleep-completed1.json'
SLEEP1 = 'tests/data/marathon/apps/sleep1.json'
SLEEP2 = 'tests/data/marathon/apps/sleep2.json'
FOLLOW = 'tests/data/file/follow.json'
TWO_TASKS = 'tests/data/file/two_tasks.json'
TWO_TASKS_FOLLOW = 'tests/data/file/two_tasks_follow.json'
LS = 'tests/data/tasks/ls-app.json'
SH = 'tests/data/tasks/sh-app.json'
CAT = 'tests/data/tasks/cat-app.json'
HELLO_STDERR = 'tests/data/marathon/apps/hello-stderr.json'

INIT_APPS = ((LS, 'ls-app'),
             (SH, 'sh-app'),
             (CAT, 'cat-app'),
             (SLEEP1, 'test-app1'),
             (SLEEP2, 'test-app2'))
NUM_TASKS = len(INIT_APPS)


def setup_module():
    # create a completed task
    with app(SLEEP_COMPLETED, 'test-app-completed'):
        pass

    for app_ in INIT_APPS:
        add_app(app_[0])


def teardown_module():
    for app_ in INIT_APPS:
        remove_app(app_[1])


def test_help():
    with open('dcoscli/data/help/task.txt') as content:
        assert_command(['dcos', 'task', '--help'],
                       stdout=content.read().encode('utf-8'))


def test_info():
    stdout = b"Manage DC/OS tasks\n"
    assert_command(['dcos', 'task', '--info'], stdout=stdout)


def test_task():
    # test `dcos task` output
    returncode, stdout, stderr = exec_command(['dcos', 'task', '--json'])

    assert returncode == 0
    assert stderr == b''

    tasks = json.loads(stdout.decode('utf-8'))
    assert isinstance(tasks, collections.Sequence)
    assert len(tasks) == NUM_TASKS

    schema = create_schema(task_fixture().dict(), True)
    schema['required'].remove('labels')

    for task in tasks:
        assert not util.validate_json(task, schema)


def test_task_table():
    assert_lines(['dcos', 'task'], NUM_TASKS + 1)


def test_task_completed():
    assert_lines(
        ['dcos', 'task', '--completed', '--json', 'test-app-completed*'],
        1,
        greater_than=True)


def test_task_all():
    assert_lines(
        ['dcos', 'task', '--json', '*-app*'],
        NUM_TASKS,
        greater_than=True)


def test_task_none():
    assert_command(['dcos', 'task', 'bogus', '--json'],
                   stdout=b'[]\n')


def test_filter():
    assert_lines(['dcos', 'task', 'test-app2', '--json'], 1, greater_than=True)


def test_log_no_files():
    """ Tail stdout on nonexistant task """
    assert_command(['dcos', 'task', 'log', 'bogus'],
                   returncode=1,
                   stderr=b'No matching tasks. Exiting.\n')


def test_log_single_file():
    """ Tail a single file on a single task """
    returncode, stdout, stderr = exec_command(
        ['dcos', 'task', 'log', 'test-app1'])

    assert returncode == 0
    assert stderr == b''
    assert len(stdout.decode('utf-8').split('\n')) > 0


def test_log_task():
    with app(HELLO_STDERR, 'test-hello-stderr'):
        returncode, stdout, stderr = exec_command(
            ['dcos', 'task', 'log', 'test-hello-stderr', 'stderr',
             '--lines=-1'])

        assert returncode == 0
        assert not stderr
        assert stdout == b'hello\n'


def test_log_missing_file():
    """ Tail a single file on a single task """
    returncode, stdout, stderr = exec_command(
        ['dcos', 'task', 'log', 'test-app2', 'bogus'])

    assert returncode == 1
    assert stdout == b''
    assert stderr == b'No logs found\n'


def test_log_lines_invalid():
    """ Test invalid --lines value """
    assert_command(['dcos', 'task', 'log', 'test-app1', '--lines=bogus'],
                   stdout=b'',
                   stderr=b'Error parsing string as int\n',
                   returncode=1)


@pytest.mark.skipif(sys.platform == 'win32',
                    reason="Using Windows unsupported import (fcntl)")
def test_log_follow():
    """ Test --follow """
    # verify output
    with app(FOLLOW, 'follow'):
        proc = subprocess.Popen(['dcos', 'task', 'log', 'follow', '--follow'],
                                stdout=subprocess.PIPE)

        # mark stdout as non-blocking, so we can read all available data
        # before EOF
        _mark_non_blocking(proc.stdout)

        time.sleep(10)
        assert len(_read_lines(proc.stdout)) >= 1

        proc.kill()


def test_log_completed():
    """ Test `dcos task log --completed` """
    with app(SLEEP_COMPLETED1, 'test-app-completed1'):
        task_id_completed = _get_task_id('test-app-completed1')

    # create a completed task
    # ensure that tail lists nothing
    # ensure that tail --completed lists a completed task
    returncode, stdout, stderr = exec_command(
        ['dcos', 'task', 'log', task_id_completed])

    assert returncode == 1
    assert stdout == b''
    assert stderr.startswith(b'No running tasks match ID [test-app-completed')

    returncode, stdout, stderr = exec_command(
        ['dcos', 'task', 'log', '--completed', task_id_completed, 'stderr'])
    assert returncode == 0
    assert stderr == b''
    assert len(stdout.decode('utf-8').split('\n')) >= 3

    returncode, stdout, stderr = exec_command(
        ['dcos', 'task', 'log', '--all', task_id_completed, 'stderr'])
    assert returncode == 0
    assert stderr == b''
    assert len(stdout.decode('utf-8').split('\n')) >= 3


def test_ls_no_params():
    returncode, stdout, stderr = exec_command(
        ['dcos', 'task', 'ls'])

    assert returncode == 0
    assert stderr == b''

    ls_line = '.*stderr.*stdout.*'
    lines = stdout.decode('utf-8').rstrip().split('\n')
    num_expected_lines = NUM_TASKS * 2

    assert len(lines) == num_expected_lines
    for i in range(0, num_expected_lines, 2):
        assert re.match('===>.*<===', lines[i])
        assert re.match(ls_line, lines[i + 1])


def test_ls():
    returncode, stdout, stderr = exec_command(
        ['dcos', 'task', 'ls', 'test-app1'])

    assert returncode == 0
    assert stderr == b''

    ls_line = '.*stderr.*stdout.*'
    lines = stdout.decode('utf-8').rstrip().split('\n')
    num_expected_lines = 1

    assert len(lines) == num_expected_lines
    assert re.match(ls_line, lines[0])


def test_ls_multiple_tasks():
    returncode, stdout, stderr = exec_command(
        ['dcos', 'task', 'ls', 'test-app'])

    assert returncode == 0
    assert stderr == b''

    ls_line = '.*stderr.*stdout.*'
    lines = stdout.decode('utf-8').rstrip().split('\n')
    num_expected_lines = 4

    for i in range(0, num_expected_lines, 2):
        assert re.match('===>.*<===', lines[i])
        assert re.match(ls_line, lines[i + 1])


def test_ls_long():
    assert_lines_range(['dcos', 'task', 'ls', '--long', 'test-app1'], 5, 7)


def test_ls_path():
    assert_command(['dcos', 'task', 'ls', 'ls-app', 'test'],
                   stdout=b'test1  test2\n')


def test_ls_bad_path():
    assert_command(
        ['dcos', 'task', 'ls', 'test-app1', 'bogus'],
        stderr=b'Cannot access [bogus]: No such file or directory\n',
        returncode=1)


def test_ls_completed():
    with app(SLEEP_COMPLETED1, 'test-app-completed1'):
        task_id_completed = _get_task_id('test-app-completed1')

    returncode, stdout, stderr = exec_command(
        ['dcos', 'task', 'ls', task_id_completed])

    assert returncode == 1
    assert stdout == b''

    err = b'Cannot find a task with ID containing "test-app-completed1'
    assert stderr.startswith(err)

    returncode, stdout, stderr = exec_command(
        ['dcos', 'task', 'ls', '--completed', task_id_completed])

    assert returncode == 0
    assert stderr == b''

    ls_line = '.*stderr.*stdout.*'
    lines = stdout.decode('utf-8').rstrip().split('\n')
    num_expected_lines = 1

    assert len(lines) == num_expected_lines
    assert re.match(ls_line, lines[0])


@pytest.mark.skipif(sys.platform == 'win32',
                    reason="'dcos task exec' not supported on Windows")
def test_exec_non_interactive():
    with open('tests/data/tasks/lorem-ipsum.txt') as text:
        content = text.read()

    task_id = _get_task_id('test-app1')

    with open('tests/data/tasks/lorem-ipsum.txt') as text:
        assert_command(
            ['dcos', 'task', 'exec', task_id, 'printf', content],
            stdout=bytes(content, 'UTF-8'))


@pytest.mark.skipif(sys.platform == 'win32',
                    reason="'dcos task exec' not supported on Windows")
def test_exec_interactive():
    with open('tests/data/tasks/lorem-ipsum.txt') as text:
        content = bytes(text.read(), 'UTF-8')

    task_id = _get_task_id('test-app1')

    with open('tests/data/tasks/lorem-ipsum.txt') as text:
        assert_command(
            ['dcos', 'task', 'exec', '--interactive', task_id, 'cat'],
            stdout=content, stdin=text)


@pytest.mark.skipif(sys.platform == 'win32',
                    reason="'dcos task exec' not supported on Windows")
def test_exec_match_id_pattern():
    assert_command(['dcos', 'task', 'exec', 'app1', 'true'])
    assert_command(['dcos', 'task', 'exec', 'app2', 'true'])
    returncode, _, _ = exec_command(['dcos', 'task', 'exec', 'app', 'true'])
    assert returncode != 0


@pytest.mark.skipif(sys.platform == 'win32',
                    reason="'dcos task exec' not supported on Windows")
def test_exec_exit_status():
    assert_command(
        ['dcos', 'task', 'exec', 'app1', 'true'],
        returncode=0)
    assert_command(
        ['dcos', 'task', 'exec', 'app1', 'bash', '-c', 'exit 10'],
        returncode=10)


@pytest.mark.skipif(sys.platform == 'win32',
                    reason="'dcos task attach' not supported on Windows")
def test_attach():
    task_id = _get_task_id('cat-app')

    proc, master = popen_tty('dcos task attach ' + task_id)
    master = os.fdopen(master, 'w')
    tty.setraw(master, when=termios.TCSANOW)

    msg = "Hello World!\n"
    expected_output = "Hello World!\r\nHello World!\r\n"
    master.write(msg)
    master.flush()

    assert proc.stdout.read(len(expected_output)).decode() == expected_output

    master.buffer.write(b'\x10\x11')
    master.flush()

    assert proc.wait() == 0
    master.close()


@pytest.mark.skipif(sys.platform == 'win32',
                    reason="'dcos task attach' not supported on Windows")
def test_attach_no_tty():
    task_id = _get_task_id('ls-app')

    proc, master = popen_tty('dcos task attach ' + task_id)
    master = os.fdopen(master, 'w')
    tty.setraw(master, when=termios.TCSANOW)

    stdout, stderr = proc.communicate()
    assert stderr == b'Unable to attach to a task launched without a TTY.\n'

    assert proc.wait() != 0
    master.close()


def _mark_non_blocking(file_):
    import fcntl
    fcntl.fcntl(file_.fileno(), fcntl.F_SETFL, os.O_NONBLOCK)


def _install_sleep_task(app_path=SLEEP1, app_name='test-app'):
    args = ['dcos', 'marathon', 'app', 'add', app_path]
    assert_command(args)
    watch_all_deployments()


def _uninstall_helloworld(args=[]):
    assert_command(['dcos', 'package', 'uninstall', 'helloworld',
                    '--yes'] + args)


def _uninstall_sleep(app_id='test-app'):
    assert_command(['dcos', 'marathon', 'app', 'remove', app_id])


def _get_task_id(app_id):
    returncode, stdout, stderr = exec_command(
        ['dcos', 'task', '--json', app_id])
    assert returncode == 0
    tasks = json.loads(stdout.decode('utf-8'))
    assert len(tasks) == 1
    task_id = tasks[0]['id']
    return task_id


def _read_lines(raw_io):
    """Polls calls to `read()` on the given byte stream until some bytes are
    returned, or the maximum number of attempts is reached.

    :param raw_io: the byte stream to read from
    :type raw_io: io.RawIOBase
    :returns: the bytes read, decoded as UTF-8 and split into a list of lines
    :rtype: [str]
    """

    for _ in range(30):
        bytes_read = raw_io.read()
        if bytes_read is not None:
            break
        time.sleep(1)
    else:
        assert False, 'timed out trying to read bytes'

    return bytes_read.decode('utf-8').split('\n')
