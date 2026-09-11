# Autojobs documentation

This folder keeps supporting documentation out of the project root while
preserving a clear, reviewable record of how Autojobs works and has been
validated.

| Area | Purpose |
| --- | --- |
| [User guide](./user-guide/) | The visual, plain-language automation guide. |
| [Reference](./reference/) | Answer-profile and question-system behavior. |
| [Changelog](./changelog/) | Release notes preserved by version. |
| [Validation](./validation/) | Versioned test and verification records. |

The repository root intentionally keeps only the main project entry points,
build/runtime assets, and GitHub community documents:

- [`README.md`](../README.md) is the GitHub landing page.
- [`README.txt`](../README.txt) remains at the root because Windows portable
  builds place it beside `autojobs.exe`.
- [`CONTRIBUTING.md`](../CONTRIBUTING.md), [`CODE_OF_CONDUCT.md`](../CODE_OF_CONDUCT.md),
  [`SECURITY.md`](../SECURITY.md), and [`SUPPORT.md`](../SUPPORT.md) use GitHub's
  standard root-level locations.

When adding documentation, place it in the most specific folder above. Keep
historical filenames stable so a record can be traced without ambiguity.
