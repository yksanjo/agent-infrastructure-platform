#!/bin/bash
# Quick push script for Agent Infrastructure Platform

set -e

echo "======================================"
echo "Agent Infrastructure Platform - Quick Push"
echo "======================================"
echo ""

# Configuration
REPO_NAME="agent-infrastructure-platform"

echo "Step 1: Checking Git configuration..."
if ! git config --global user.name > /dev/null 2>&1; then
    echo "Error: Git user.name not set"
    echo "Run: git config --global user.name 'Your Name'"
    exit 1
fi

if ! git config --global user.email > /dev/null 2>&1; then
    echo "Error: Git user.email not set"
    echo "Run: git config --global user.email 'your@email.com'"
    exit 1
fi

echo "✓ Git configured"
echo ""

# Check for GitHub CLI
if command -v gh &> /dev/null; then
    echo "Step 2: GitHub CLI detected!"
    
    # Check if logged in
    if gh auth status &> /dev/null; then
        echo "✓ Already logged into GitHub"
        
        # Get username
        USERNAME=$(gh api user -q .login)
        echo "GitHub username: $USERNAME"
        
        read -p "Create repository '$REPO_NAME' on GitHub? (y/n): " CREATE_REPO
        
        if [[ $CREATE_REPO == "y" ]]; then
            echo "Creating repository..."
            gh repo create "$REPO_NAME" \
                --public \
                --description "The Operating System for the Trillion-Agent Economy" \
                --source=. \
                --remote=origin \
                --push
            
            echo ""
            echo "======================================"
            echo "✅ SUCCESS! Repository created and pushed!"
            echo "======================================"
            echo ""
            echo "Repository URL: https://github.com/$USERNAME/$REPO_NAME"
            echo ""
            echo "Next steps:"
            echo "1. Visit https://github.com/$USERNAME/$REPO_NAME"
            echo "2. Set up PyPI API token for automatic releases"
            echo "3. Check out DISTRIBUTION_GUIDE.md for marketing"
            echo ""
            exit 0
        fi
    else
        echo "Please login to GitHub CLI:"
        echo "  gh auth login"
        exit 1
    fi
else
    echo "GitHub CLI not found. Using manual setup..."
    echo ""
fi

# Manual setup
echo "Step 2: Manual GitHub Setup"
echo "------------------------------"
echo ""
echo "Please create a repository on GitHub:"
echo "1. Go to: https://github.com/new"
echo "2. Repository name: $REPO_NAME"
echo "3. Description: The Operating System for the Trillion-Agent Economy"
echo "4. Visibility: Public (recommended)"
echo "5. Do NOT initialize with README (we already have one)"
echo ""

read -p "Enter your GitHub username: " USERNAME

REMOTE_URL="git@github.com:${USERNAME}/${REPO_NAME}.git"

echo ""
echo "Setting up remote..."

# Check if remote exists
if git remote | grep -q "origin"; then
    git remote set-url origin "$REMOTE_URL"
else
    git remote add origin "$REMOTE_URL"
fi

echo "✓ Remote configured: $REMOTE_URL"
echo ""

# Push
echo "Pushing to GitHub..."
git push -u origin main

echo ""
echo "======================================"
echo "✅ SUCCESS! Code pushed to GitHub!"
echo "======================================"
echo ""
echo "Repository URL: https://github.com/$USERNAME/$REPO_NAME"
echo ""
echo "Next steps:"
echo "1. Visit your repository on GitHub"
echo "2. Create a release: git tag v0.1.0 && git push origin v0.1.0"
echo "3. Check out DISTRIBUTION_GUIDE.md for PyPI and Docker setup"
echo ""
