# Errors

## [ERR-20261027-POL] polarization_dependency_download

**Logged**: 2026-10-27
**Priority**: low
**Status**: resolved
**Area**: infra

### Summary
PyPI wheel metadata downloads timed out even after network access was authorized.

### Resolution
Installed validation dependencies in a temporary virtual environment using the Tsinghua PyPI mirror. The user also authorized the Aliyun mirror as a fallback. No project-wide index setting was changed.

---
