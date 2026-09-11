# Security policy

Autojobs handles local configuration and may use a dedicated, signed-in Chrome profile. Please report potential vulnerabilities privately so users have time to protect themselves.

## Supported versions

Security fixes are evaluated for the current default branch and the latest published Windows release. Older releases may require an upgrade rather than a backport.

## Reporting a vulnerability

1. If this repository has GitHub private vulnerability reporting enabled, use **Security** -> **Advisories** -> **Report a vulnerability**.
2. Otherwise, contact the repository owner privately through the contact method on their GitHub profile.
3. Do not post vulnerability details, proof-of-concept exploits, session data, credentials, or private logs in a public issue, pull request, or Discussion.

A helpful private report includes:

- A concise description of the impact
- The affected version or commit
- Clear, minimal reproduction steps
- A sanitized proof of concept or log excerpt, when safe to share
- Any suggested mitigation, if you have one

Maintainers will assess the report, coordinate a fix when appropriate, and work toward responsible disclosure. Please allow time for triage and remediation before discussing the issue publicly.

## Out of scope

Autojobs intentionally does not implement anti-abuse or access-control evasion. Feature requests intended to add CAPTCHA, 2FA, account-challenge, rate-limit, platform-restriction, or consent bypasses are outside this project's scope.

If you discover a vulnerability that unintentionally exposes private data or lets someone bypass a security boundary, report it privately under this policy.

## Maintainer setup

Before publishing the repository, maintainers should enable GitHub private vulnerability reporting in the repository's security settings. That gives reporters a confidential, repository-native path and should be the preferred channel for new security reports.
