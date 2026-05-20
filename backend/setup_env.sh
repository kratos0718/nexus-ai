#!/bin/bash
# ============================================================
# NEXUS AI — Development Environment Setup Script
# Run this ONCE to set up your conda environment
# Usage: bash setup_env.sh
# ============================================================

echo "🚀 Setting up Nexus AI development environment..."

# Create conda env with Python 3.11 (recommended for modern AI libs)
conda create -n nexus-ai python=3.11 -y

echo "✅ Conda environment 'nexus-ai' created"
echo ""
echo "Now run these commands:"
echo "  conda activate nexus-ai"
echo "  pip install -r requirements.txt"
echo ""
echo "Then start the backend:"
echo "  uvicorn app.main:app --reload --port 8000"
