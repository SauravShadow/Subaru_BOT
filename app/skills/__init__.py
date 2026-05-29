from pathlib import Path
from app.skills.loader import SkillLoader
from app import config

skill_loader = SkillLoader(config.SKILLS_DIR)
