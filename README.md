# schedula

## Deployment

The deployment entry point accepts an environment and a built artifact file:

```bash
scripts/deploy staging ./release.tar.gz
scripts/deploy production ./release.tar.gz
```

The deployment destination is undecided. The script validates its arguments and
exits with status 1 until deployment is implemented. Invalid arguments exit with
status 2. It does not build, upload, or deploy anything yet.

The release workflow will call this script with the same artifact for staging
and production. Production must wait for GitHub Environment approval. Configure
and verify Environment protections before introducing that workflow.

Pending setup: initial Git commit, an independent PR reviewer, release tag issuer,
production reviewer, real CI/build commands, and the deployment destination.
