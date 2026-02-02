# Distribution Guide

This guide walks you through publishing and distributing the Agent Infrastructure Platform.

## 📦 Table of Contents

1. [GitHub Setup](#github-setup)
2. [PyPI Distribution](#pypi-distribution)
3. [Docker Distribution](#docker-distribution)
4. [Documentation Hosting](#documentation-hosting)
5. [Marketing & Community](#marketing--community)

---

## GitHub Setup

### 1. Create GitHub Repository

```bash
# Option A: Via GitHub CLI (if installed)
gh repo create agent-infrastructure-platform \
  --public \
  --description "The Operating System for the Trillion-Agent Economy" \
  --source=. \
  --remote=origin \
  --push

# Option B: Manual setup
# 1. Go to https://github.com/new
# 2. Name: agent-infrastructure-platform
# 3. Description: The Operating System for the Trillion-Agent Economy
# 4. Visibility: Public
# 5. Don't initialize with README (we already have one)
```

### 2. Push Your Code

```bash
# If you ran the setup script:
chmod +x setup_github_remote.sh
./setup_github_remote.sh

# Or manually:
git remote add origin git@github.com:YOUR_USERNAME/agent-infrastructure-platform.git
git branch -M main
git push -u origin main
```

### 3. Create a Release

```bash
# Tag the release
git tag -a v0.1.0 -m "Initial release v0.1.0"
git push origin v0.1.0

# Or via GitHub CLI
gh release create v0.1.0 \
  --title "v0.1.0 - Initial Release" \
  --notes "First release of the Agent Infrastructure Platform"
```

---

## PyPI Distribution

### 1. Build the Package

```bash
# Install build dependencies
pip install build twine

# Build the package
python -m build

# Check the build
twine check dist/*
```

### 2. Publish to PyPI

```bash
# Test on TestPyPI first
twine upload --repository testpypi dist/*

# Install from TestPyPI to verify
pip install --index-url https://test.pypi.org/simple/ agent-infrastructure-platform

# Publish to PyPI
twine upload dist/*
```

### 3. Verify Installation

```bash
pip install agent-infrastructure-platform
python -c "import agent_infrastructure_platform; print('✓ Installed successfully')"
```

---

## Docker Distribution

### 1. Build Docker Image

```bash
# Build the image
docker build -t agent-infrastructure-platform:latest .
docker build -t agent-infrastructure-platform:v0.1.0 .

# Test locally
docker run -p 8000:8000 agent-infrastructure-platform:latest
```

### 2. Push to Docker Hub

```bash
# Login
docker login

# Tag for Docker Hub
docker tag agent-infrastructure-platform:latest YOUR_DOCKERHUB_USER/agent-infrastructure-platform:latest
docker tag agent-infrastructure-platform:v0.1.0 YOUR_DOCKERHUB_USER/agent-infrastructure-platform:v0.1.0

# Push
docker push YOUR_DOCKERHUB_USER/agent-infrastructure-platform:latest
docker push YOUR_DOCKERHUB_USER/agent-infrastructure-platform:v0.1.0
```

### 3. Push to GitHub Container Registry

```bash
# Login to GHCR
echo $GITHUB_TOKEN | docker login ghcr.io -u YOUR_USERNAME --password-stdin

# Tag for GHCR
docker tag agent-infrastructure-platform:latest ghcr.io/YOUR_USERNAME/agent-infrastructure-platform:latest

# Push
docker push ghcr.io/YOUR_USERNAME/agent-infrastructure-platform:latest
```

---

## Documentation Hosting

### Option 1: GitHub Pages (Recommended)

```bash
# Install MkDocs
pip install mkdocs mkdocs-material

# Create mkdocs.yml
cat > mkdocs.yml << 'EOF'
site_name: Agent Infrastructure Platform
theme:
  name: material
  palette:
    - scheme: default
      primary: blue
      toggle:
        icon: material/brightness-7
        name: Switch to dark mode
    - scheme: slate
      primary: blue
      toggle:
        icon: material/brightness-4
        name: Switch to light mode
nav:
  - Home: index.md
  - Architecture: architecture.md
  - API Reference: api.md
  - Examples: examples.md
plugins:
  - search
EOF

# Deploy to GitHub Pages
mkdocs gh-deploy
```

### Option 2: Read the Docs

1. Go to https://readthedocs.org/
2. Import your GitHub repository
3. Configure `.readthedocs.yml` in your repo
4. Documentation will auto-build on pushes

---

## Marketing & Community

### 1. README Badges

Add these badges to your README.md:

```markdown
[![PyPI version](https://badge.fury.io/py/agent-infrastructure-platform.svg)](https://badge.fury.io/py/agent-infrastructure-platform)
[![Python Versions](https://img.shields.io/pypi/pyversions/agent-infrastructure-platform.svg)](https://pypi.org/project/agent-infrastructure-platform/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Tests](https://github.com/YOUR_USERNAME/agent-infrastructure-platform/actions/workflows/tests.yml/badge.svg)](https://github.com/YOUR_USERNAME/agent-infrastructure-platform/actions)
[![Docker](https://img.shields.io/docker/pulls/YOUR_DOCKERHUB_USER/agent-infrastructure-platform)](https://hub.docker.com/r/YOUR_DOCKERHUB_USER/agent-infrastructure-platform)
```

### 2. Social Media Announcements

**Twitter/X Post:**
```
🚀 Just launched the Agent Infrastructure Platform!

The operating system for the trillion-agent economy:
✅ 4 communication protocols (MCP, A2A, ACP, ANP)
✅ Distributed identity & trust
✅ Economic layer with micropayments
✅ Governance & safety infrastructure

GitHub: https://github.com/YOUR_USERNAME/agent-infrastructure-platform
Docs: https://YOUR_USERNAME.github.io/agent-infrastructure-platform

#AI #Agents #MultiAgent #OpenSource
```

**LinkedIn Post:**
```
Excited to announce the release of the Agent Infrastructure Platform (AIP) - a comprehensive framework for building, deploying, and governing multi-agent systems at scale.

What makes AIP unique:
🔹 Protocol-native (MCP, A2A, ACP, ANP)
🔹 Decentralized identity & trust
🔹 Built-in economic incentives
🔹 Production-ready governance

Perfect for anyone building the next generation of AI agent systems.

Check it out: [GitHub link]

#ArtificialIntelligence #MultiAgentSystems #OpenSource #DeveloperTools
```

**Hacker News Post:**
```
Show HN: Agent Infrastructure Platform – The OS for the Trillion-Agent Economy

We've built a comprehensive infrastructure platform for multi-agent systems that provides:

- Universal protocols (MCP, A2A, ACP, ANP)
- Distributed identity with verifiable credentials
- Economic layer with micropayments and staking
- Governance with policy-as-code and kill switches
- 10k+ concurrent agent support

GitHub: https://github.com/YOUR_USERNAME/agent-infrastructure-platform

Would love feedback from the community!
```

### 3. Reddit Communities

Post to:
- r/MachineLearning
- r/artificial
- r/Python
- r/programming
- r/coding

### 4. Developer Forums

- **Dev.to**: Write a technical deep-dive article
- **Medium**: Publish on Towards Data Science
- **Hashnode**: Developer-focused tutorial

### 5. Email Newsletter

```markdown
Subject: Introducing Agent Infrastructure Platform v0.1.0

Hi [Name],

I'm excited to share the initial release of the Agent Infrastructure Platform (AIP) - a comprehensive, production-ready infrastructure for building multi-agent systems.

Key Features:
• Universal Communication Protocols (MCP, A2A, ACP, ANP)
• Distributed Identity & Trust Layer
• Shared Memory & State Infrastructure
• Economic & Incentive Layer
• Governance & Safety Infrastructure

Get started: pip install agent-infrastructure-platform
GitHub: https://github.com/YOUR_USERNAME/agent-infrastructure-platform

I'd love your feedback and contributions!

Best,
[Your Name]
```

---

## 📊 Post-Launch Checklist

- [ ] GitHub repo created and pushed
- [ ] PyPI package published
- [ ] Docker image published
- [ ] Documentation hosted
- [ ] README badges added
- [ ] Social media announcements posted
- [ ] Reddit posts created
- [ ] Dev.to/Medium articles published
- [ ] GitHub discussions enabled
- [ ] Issue templates created
- [ ] Contributing guidelines visible

---

## 🎯 Success Metrics

Track these metrics:

| Metric | Target (30 days) |
|--------|-----------------|
| GitHub Stars | 100+ |
| PyPI Downloads | 500+ |
| Docker Pulls | 200+ |
| Contributors | 5+ |
| Issues Created | 10+ |
| Forks | 20+ |

---

**Good luck with your launch! 🚀**
