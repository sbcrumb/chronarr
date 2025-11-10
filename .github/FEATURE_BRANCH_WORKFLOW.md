# Feature Branch Docker Build Workflow

This workflow automatically builds Docker images for feature branches and publishes them to GitHub Container Registry (ghcr.io) instead of Docker Hub.

## How It Works

### Automatic Builds

When you push to these branch patterns, a Docker image is automatically built:
- `feature/*` (e.g., `feature/add-new-api`)
- `feat/*` (e.g., `feat/improve-performance`)
- `fix/*` (e.g., `fix/database-connection`)

The image is pushed to: `ghcr.io/sbcrumb/chronarr:feature-branch-name`

### Branch Naming Examples

```bash
# These will trigger builds:
git checkout -b feature/jellyfin-sync
git checkout -b feat/async-processing
git checkout -b fix/memory-leak

# Branch name with / becomes - in Docker tag:
feature/jellyfin-sync  →  ghcr.io/sbcrumb/chronarr:feature-jellyfin-sync
```

## Using Feature Branch Images

### 1. Pull the Image

```bash
# After GitHub Actions completes, pull your feature branch image
docker pull ghcr.io/sbcrumb/chronarr:feature-jellyfin-sync
```

### 2. Update docker-compose.yml

Edit your `docker-compose.yml` to use the feature branch image:

```yaml
services:
  chronarr-core:
    image: ghcr.io/sbcrumb/chronarr:feature-jellyfin-sync  # Feature branch
    # ... rest of config

  chronarr-web:
    image: ghcr.io/sbcrumb/chronarr:feature-jellyfin-sync  # Feature branch
    # ... rest of config
```

### 3. Test Your Changes

```bash
docker-compose down
docker-compose up -d
```

### 4. Merge to Main

Once tested, merge your feature branch:

```bash
git checkout main
git merge feature/jellyfin-sync
git push origin main
```

### 5. Delete Feature Branch

```bash
git branch -d feature/jellyfin-sync
git push origin --delete feature/jellyfin-sync
```

**Note**: You'll need to manually delete the Docker image from GitHub Container Registry after deleting the branch.

## Workflow Benefits

### ✅ Advantages

- **No Docker Hub pollution**: Feature branches don't clutter your Docker Hub
- **Easy testing**: Pull and test any feature branch image
- **Free storage**: GitHub Container Registry is free for public repos
- **Automatic builds**: No manual docker build commands
- **PR integration**: Images build on pull requests too

### 📊 Image Management

**Main/Dev Branches**: Still push to Docker Hub (existing workflow)
- `sbcrumb/chronarr:latest` (main branch)
- `sbcrumb/chronarr:dev` (dev branch)

**Feature Branches**: Push to GitHub Container Registry
- `ghcr.io/sbcrumb/chronarr:feature-*`
- `ghcr.io/sbcrumb/chronarr:feat-*`
- `ghcr.io/sbcrumb/chronarr:fix-*`

## Accessing GitHub Container Registry

### Authentication

The workflow uses `GITHUB_TOKEN` automatically. To pull images locally:

```bash
# Create a GitHub personal access token with package:read scope
# Then login:
echo $GITHUB_TOKEN | docker login ghcr.io -u USERNAME --password-stdin
```

### Public Images

If your repository is public, the images are public by default. No authentication needed to pull!

## Cleanup

### Manual Cleanup

To delete old feature branch images:

1. Go to: `https://github.com/sbcrumb?tab=packages`
2. Find the `chronarr` package
3. Click on it
4. Find the tag for your deleted branch
5. Click "..." → "Delete version"

### Automatic Cleanup (Future)

The `cleanup-feature-images.yml` workflow provides notes for manual cleanup. GitHub doesn't support automatic image deletion on branch delete yet.

## Workflow Files

- **`.github/workflows/feature-branch.yml`** - Builds images for feature branches
- **`.github/workflows/cleanup-feature-images.yml`** - Cleanup reminder on branch delete

## Example Workflow

```bash
# 1. Create feature branch
git checkout -b feature/new-api

# 2. Make changes and push
git add .
git commit -m "Add new API endpoint"
git push origin feature/new-api

# 3. Wait for GitHub Actions (~2-5 minutes)
# Check: https://github.com/sbcrumb/chronarr/actions

# 4. Pull the feature branch image
docker pull ghcr.io/sbcrumb/chronarr:feature-new-api

# 5. Test with docker-compose
# Edit docker-compose.yml to use the feature image
docker-compose up -d

# 6. Verify everything works
# Test your changes

# 7. Merge to main
git checkout main
git merge feature/new-api
git push origin main

# 8. Delete feature branch
git push origin --delete feature/new-api

# 9. Clean up Docker image (manual)
# Go to GitHub packages and delete the feature-new-api tag
```

## Troubleshooting

### Build Fails

Check the GitHub Actions logs:
- Go to Actions tab in GitHub
- Click on the failed workflow
- Review build logs

### Can't Pull Image

Verify the image exists:
```bash
# Check available tags
docker search ghcr.io/sbcrumb/chronarr --limit 100
```

Or check GitHub: `https://github.com/sbcrumb/chronarr/pkgs/container/chronarr`

### Image Size

Feature branch images use build cache to speed up builds. First build may be slow, subsequent builds are faster.
