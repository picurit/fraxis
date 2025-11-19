from json import dumps
from frappe import _dict

class DotDict(_dict):
    """Dictionary that supports dot notation access to attributes"""
    
    def as_dict(self) -> dict:
        """Convert DotDict to a standard dictionary"""
        return dict(self)
    
    def to_json(self) -> str:
        """Convert DotDict to a JSON string"""
        return dumps(self)