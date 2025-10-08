@echo off
REM ===========================================
REM Setup script for Writingway
REM ===========================================

REM Check if the virtual environment folder exists.
IF NOT EXIST "venv" (
    echo Creating virtual environment...
    conda create -n writingway
) ELSE (
    echo Virtual environment already exists.
)

REM Activate the virtual environment.
echo Activating virtual environment...
conda activate writingway

REM Upgrade pip.
echo Upgrading pip...
python -m pip install --upgrade pip

REM Upgrade setuptools.
echo Upgrading setuptools...
python -m pip install --upgrade setuptools

REM Install required packages from requirements.txt.
echo Installing dependencies from requirements.txt...
pip install -r requirements.txt

REM Install spaCy English model if not already installed.
echo Installing spaCy English model...
python -m spacy download en_core_web_sm

REM Add BeautifulSoup4 so that statistics.py can extract text from HTML files
python -m pip install beautifulsoup4

echo.
echo Setup complete!
pause
