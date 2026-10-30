"""Platform facts every module may import; imports nothing from src, so it never takes part in a cycle."""
import os

IS_WINDOWS = os.name == "nt"
