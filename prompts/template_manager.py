import os
from jinja2 import Environment, FileSystemLoader, TemplateNotFound

class TemplateManager:
    """Manages loading and rendering of Jinja2 prompt templates."""
    def __init__(self, templates_dir: str = None):
        if templates_dir is None:
            # Default templates path: prompts/templates
            current_dir = os.path.dirname(os.path.abspath(__file__))
            templates_dir = os.path.join(current_dir, "templates")
            
        self.env = Environment(loader=FileSystemLoader(templates_dir))

    def render(self, template_name: str, **kwargs) -> str:
        """Load and render a template with the provided context arguments."""
        try:
            template = self.env.get_template(template_name)
            return template.render(**kwargs)
        except TemplateNotFound:
            raise FileNotFoundError(f"Prompt template '{template_name}' not found.")

# Singleton instance for easy reuse
manager = TemplateManager()
