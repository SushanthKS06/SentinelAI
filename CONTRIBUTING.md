# Contributing to SentinelAI

Thank you for your interest in contributing to SentinelAI!

## Development Environment

### Prerequisites

- Docker 24.0+
- Python 3.11+
- Node.js 18+
- PostgreSQL 15+
- Redis 7+
- Kafka 3.6+

### Setup

```bash
# Clone the repository
git clone https://github.com/sentinelai/sentinelai.git
cd sentinelai

# Install dependencies
pip install -e .

# Start infrastructure
docker-compose -f infrastructure/docker-compose.yml up -d

# Run tests
make test

# Start development server
make dev
```

## Code Style

- **Python**: Follow PEP 8, use Black for formatting
- **TypeScript**: Follow ESLint rules
- **Commits**: Use conventional commits format

## Pull Request Process

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/amazing-feature`)
3. Make your changes and add tests
4. Ensure all tests pass
5. Commit with conventional commit messages
6. Push to your fork and submit a PR

## Commit Message Format

```
<type>(<scope>): <description>

[optional body]

[optional footer]
```

Types: `feat`, `fix`, `docs`, `style`, `refactor`, `test`, `chore`

## Testing

```bash
# Run all tests
make test

# Run specific test suite
pytest tests/unit

# Run with coverage
make coverage
```

## Reporting Issues

Use GitHub Issues to report bugs or request features. Include:
- Clear description
- Steps to reproduce
- Environment details
- Screenshots if applicable

## Code of Conduct

Be respectful and inclusive. Follow the [Contributor Covenant](https://www.contributor-covenant.org/).

## License

By contributing, you agree that your contributions will be licensed under Apache License 2.0.
