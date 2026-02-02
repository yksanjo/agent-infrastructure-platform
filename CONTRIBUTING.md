# Contributing to Agent Infrastructure Platform

Thank you for your interest in contributing to AIP! This document provides guidelines and instructions for contributing.

## Getting Started

1. Fork the repository
2. Clone your fork: `git clone https://github.com/YOUR_USERNAME/agent-infrastructure-platform`
3. Install dependencies: `pip install -e ".[dev]"`
4. Create a branch: `git checkout -b feature/your-feature`

## Development Setup

```bash
# Install development dependencies
pip install -e ".[dev]"

# Run tests
pytest

# Run type checker
mypy src

# Run linter
ruff check .

# Format code
ruff format .
```

## Pull Request Process

1. Ensure tests pass
2. Update documentation
3. Add entry to CHANGELOG.md
4. Submit PR with clear description

## Code Style

- Follow PEP 8
- Use type hints
- Write docstrings
- Keep functions focused

## Commit Messages

Use conventional commits:
- `feat: add new feature`
- `fix: bug fix`
- `docs: documentation`
- `test: add tests`
- `refactor: code refactoring`

## License

By contributing, you agree that your contributions will be licensed under the MIT License.
