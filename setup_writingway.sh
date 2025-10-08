#!/bin/bash
# ===========================================
# Setup script for Writingway (macOS)
# ===========================================

# Check if the virtual environment folder exists.
if [ ! -d "venv" ]; then
  echo "Creating virtual environment..."
  conda create -n writingway
  # python -m venv venv
else
  echo "Virtual environment already exists."
fi

# Activate the virtual environment.
echo "Activating virtual environment..."
conda activate writingway
# source venv/bin/activate

# Upgrade pip.
echo "Upgrading pip..."
python -m pip install --upgrade pip

# Upgrade setuptools.
echo "Upgrading setuptools..."
python -m pip install --upgrade setuptools

# Install required packages from requirements.txt.
echo "Installing dependencies from requirements.txt..."
pip install -r requirements.txt

# Install spaCy English model if not already installed.
echo "Installing spaCy English model..."
python -m spacy download en_core_web_sm

# Add BeautifulSoup4 so that statistics.py can extract text from HTML files
python -m pip install beautifulsoup4

echo ""
echo "Setup complete!"

read -p "Press Enter to continue..."