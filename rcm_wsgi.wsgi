import sys
import os

os.environ['LANG'] = 'C.UTF-8'
os.environ['LC_ALL'] = 'C.UTF-8'
os.environ['PYTHONIOENCODING'] = 'utf-8'


# Define the project path
project_home = '/root/RCM_7021'
if project_home not in sys.path:
    sys.path.insert(0, project_home)

# Set working directory to project home
os.chdir(project_home)

# Import the flask application instance from app.py
from app import app as application
