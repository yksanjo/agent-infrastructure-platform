#!/bin/bash
# Setup GitHub remote for Agent Infrastructure Platform

set -e

echo "======================================"
echo "GitHub Remote Setup"
echo "======================================"
echo ""

# Get GitHub username
read -p "Enter your GitHub username: " USERNAME

# Set repository name (default: agent-infrastructure-platform)
read -p "Repository name [agent-infrastructure-platform]: " REPO_NAME
REPO_NAME=${REPO_NAME:-agent-infrastructure-platform}

# Create remote URL
REMOTE_URL="git@github.com:${USERNAME}/${REPO_NAME}.git"

echo ""
echo "Setting up remote: $REMOTE_URL"

# Check if remote exists
if git remote | grep -q "origin"; then
    echo "Remote 'origin' exists. Updating..."
    git remote set-url origin "$REMOTE_URL"
else
    echo "Adding remote 'origin'..."
    git remote add origin "$REMOTE_URL"
fi

echo ""
echo "Remote configured:"
git remote -v

echo ""
echo "======================================"
echo "Next steps:"
echo "======================================"
echo "1. Create the repository on GitHub:"
echo "   https://github.com/new"
echo "   Name: $REPO_NAME"
echo "   Visibility: Public (or Private)"
echo ""
echo "2. Then push with:"
echo "   git push -u origin main"
echo ""
