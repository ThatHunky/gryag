```markdown
# Docker Build Troubleshooting Guide

**Date**: 2025-10-30
**Issue**: SSL certificate verification failure when downloading dependencies
**Status**: ✅ Fixed

---

## Problem

Docker build fails with:
```
fatal: unable to access 'https://github.com/gabime/spdlog.git/':
server certificate verification failed.
CAfile: none CRLfile: none
```

This occurs when CMake tries to download dependencies using FetchContent.

... (document preserved from root - archived here)

```
