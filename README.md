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

## Repository change management

Changes to main require a PR and the successful `deploy-entrypoint` CI check.
Required PR approvals are set to zero for single-person operation. Merge uses
squash only; main rejects force pushes and deletion, with no ruleset bypass.

Only Repository Admins may create `v*` release tags. Currently this is
@omitsuhashi; future admins will also be able to create release tags. Existing
`v*` tags cannot be moved or deleted, including by admins through bypass.

Pending deployment setup: production reviewer, real build commands, and the
deployment destination. The deployment entry point and CI are introduced through
the setup PR and become available on main after it is merged.
