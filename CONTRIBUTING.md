# Contributing to MrBekoXBlogApp

Thank you for your interest in contributing!

## Code of Conduct

- Be respectful and inclusive
- Provide constructive feedback
- Focus on what is best for the community

## How to Contribute

### Reporting Bugs

1. Check existing issues
2. Create a new issue with:
   - Clear title
   - Steps to reproduce
   - Expected vs actual behavior
   - Environment details

### Suggesting Features

1. Check existing issues and feature requests
2. Create a new issue with:
   - Feature description
   - Use case
   - Potential implementation approach

### Pull Requests

1. Fork the repository
2. Create a feature branch: `git checkout -b feature/my-feature`
3. Make your changes
4. Write/update tests
5. Ensure code passes linting
6. Commit with clear messages
7. Push and create a pull request

### Coding Standards

#### C# (.NET)
- Follow C# coding conventions
- Use XML documentation for public APIs
- Write unit tests for new features
- Keep methods small and focused

#### TypeScript/React
- Use functional components with hooks
- Follow TypeScript best practices
- Use proper typing (no `any`)
- Follow ESLint rules

#### Python
- Follow PEP 8 style guide
- Use type hints
- Write docstrings for functions
- Follow Python naming conventions

### Commit Messages

Use conventional commits:

- `feat:` New feature
- `fix:` Bug fix
- `docs:` Documentation changes
- `style:` Code style changes
- `refactor:` Code refactoring
- `test:` Test additions/changes
- `chore:` Build/process changes

Example:
```
feat(auth): add refresh token support

Implement JWT refresh token rotation for improved security.
- Add refresh token endpoint
- Store refresh tokens in database
- Implement token rotation logic
```

## Development Setup

See README.md for detailed setup instructions.

## Getting Help

- Open an issue for bugs or feature requests
- Check existing documentation
- Start a discussion for questions
