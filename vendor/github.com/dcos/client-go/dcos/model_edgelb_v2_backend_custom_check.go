/*
 * DC/OS
 *
 * DC/OS API
 *
 * API version: 1.0.0
 */

// Code generated by OpenAPI Generator (https://openapi-generator.tech); DO NOT EDIT.

package dcos

// This is used to specify alternate forms of healthchecks
type EdgelbV2BackendCustomCheck struct {
	Httpchk        bool   `json:"httpchk,omitempty"`
	HttpchkMiscStr string `json:"httpchkMiscStr,omitempty"`
	SslHelloChk    bool   `json:"sslHelloChk,omitempty"`
	MiscStr        string `json:"miscStr,omitempty"`
}