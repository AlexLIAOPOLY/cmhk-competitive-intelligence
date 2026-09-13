"""Web application domains; web_app.py remains the public startup facade.

Domain binders receive the owning application explicitly. Functions resolve
shared configuration, locks and collaborators from that context at call time,
so existing imports and test patches through web_app retain their behavior.
"""
