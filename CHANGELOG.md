# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [1.0.0] - 2026-10-31

### Added
- Live staging integration tests for eight service flows (`integration/`) (DDP-#66)
- Playwright UI tests for the three critical flows: register and log in, browse and enrol, take an exam (`e2e/`, run manually through `e2e.yml`) (DDP-#68)
- Performance tests: a latency and concurrency load script with a stop rule for unhealthy steps and a count of transport failures (`performance/`) (DDP-#70)
- Lint and security-scan stages for the tests pipeline (`quality.yml`) (DDP-#57)
- PayHere webhook integration tests against an in-process mock gateway (DDP-#29)
- Smoke test runs after each staging deploy
- `.env.example` documenting every required environment variable (DDP-#54)
- `testing/` folder with the testing notes; README badges, deployed links, prerequisites and run steps

### Changed
- Smoke test aligned with the current API (PR #10)
- Hardcoded secret defaults removed from the tests; secrets are read from the environment (DDP-#54)

### Fixed
- Load test formatting (`black`) after merging the performance branch

## [0.3.0] - 2026-10-15

Tagged retrospectively for Sprint 7 (11 Aug to 7 Sep 2026); the tag points at the first test commit of 15 October 2026.

### Added
- Critical-path smoke test: register, verify, log in, enrol and view a course on staging (DDP-#24)

## [0.2.0] - 2026-06-23

Tagged retrospectively for Sprint 6 (14 Jul to 10 Aug 2026). No changes in this repository during the sprint; the tag points at the same commit as v0.1.0.

## [0.1.0] - 2026-06-23

Tagged retrospectively for Sprint 5 (16 Jun to 13 Jul 2026).

### Added
- Test suite repository files and Python tooling configuration

[Unreleased]: https://github.com/Edura-LMS-Zynaptrix/edura-tests/compare/v1.0.0...develop
[1.0.0]: https://github.com/Edura-LMS-Zynaptrix/edura-tests/compare/v0.3.0...v1.0.0
[0.3.0]: https://github.com/Edura-LMS-Zynaptrix/edura-tests/compare/v0.2.0...v0.3.0
[0.2.0]: https://github.com/Edura-LMS-Zynaptrix/edura-tests/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/Edura-LMS-Zynaptrix/edura-tests/releases/tag/v0.1.0
