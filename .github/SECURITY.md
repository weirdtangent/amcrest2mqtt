# Security Policy

## Supported Versions

| Version | Supported          |
| ------- | ------------------ |
| latest  | :white_check_mark: |
| < 2.0   | :x:                |

## Reporting a Vulnerability

If you discover a security vulnerability in this project, please report it responsibly:

1. **Do not** open a public GitHub issue for security vulnerabilities
2. Email the maintainer directly or use [GitHub's private vulnerability reporting](https://github.com/weirdtangent/amcrest2mqtt/security/advisories/new)
3. Include as much detail as possible:
   - Description of the vulnerability
   - Steps to reproduce
   - Potential impact
   - Suggested fix (if any)

You can expect an initial response within 48 hours. We will work with you to understand and address the issue promptly.

## Security Measures

This project implements several security measures:

- **SBOM (Software Bill of Materials)**: Every Docker image includes a complete list of dependencies
- **Provenance Attestation**: Build provenance is attached to images to verify where and how they were built
- **Image Signing**: Images are signed using [Sigstore Cosign](https://www.sigstore.dev/) for authenticity verification
- **Vulnerability Scanning**: Images are scanned with [Trivy](https://trivy.dev/) for known vulnerabilities

### Verifying Image Signatures

You can verify the signature of our Docker images using cosign:

```bash
cosign verify graystorm/amcrest2mqtt:latest \
  --certificate-identity-regexp="https://github.com/weirdtangent/amcrest2mqtt" \
  --certificate-oidc-issuer="https://token.actions.githubusercontent.com"
```
