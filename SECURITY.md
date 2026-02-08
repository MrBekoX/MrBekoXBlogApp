# Security Policy

## Supported Versions

| Version | Supported          |
|---------|--------------------|
| 0.1.x   | :white_check_mark: |

## Reporting a Vulnerability

If you discover a security vulnerability, please **do not open a public issue**.

Instead, send an email to: security@example.com

Please include:
- Description of the vulnerability
- Steps to reproduce
- Potential impact
- Suggested fix (if known)

### Response Timeline

- **Initial Response**: Within 48 hours
- **Detailed Response**: Within 7 days
- **Fix Release**: As soon as validated

### Security Best Practices

This project implements:
- JWT authentication with secure token validation
- Rate limiting on all endpoints
- Input sanitization for HTML content
- CORS protection
- CSRF protection
- SQL injection prevention (EF Core parameterization)
- Security headers (HSTS, X-Frame-Options, etc.)

## Security Audits

This project has not yet undergone a professional security audit.

## Dependencies

We regularly update dependencies to address known vulnerabilities. Please keep your dependencies updated.
