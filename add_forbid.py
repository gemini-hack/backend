import os
import re

schema_dir = 'app/schemas'

for root, _, files in os.walk(schema_dir):
    for file in files:
        if file.endswith('.py') and file != '__init__.py':
            path = os.path.join(root, file)
            with open(path, 'r') as f:
                content = f.read()
            
            # Ensure ConfigDict is imported from pydantic
            if 'ConfigDict' not in content and 'pydantic' in content:
                content = re.sub(r'(from pydantic import(?:.+))', r'\1, ConfigDict', content, 1)
            
            lines = content.split('\n')
            new_lines = []
            
            in_input_schema = False
            schema_name = ""
            
            for i, line in enumerate(lines):
                new_lines.append(line)
                
                # Check if it's a class definition for an input schema
                match = re.match(r'^class\s+([A-Za-z0-9_]+(?:Create|Update|Base|Request|Input|PatientBase|ConditionBase))\b.*:', line)
                if match:
                    # It's an input schema.
                    schema_name = match.group(1)
                    
                    # Look ahead to see if model_config already exists
                    has_config = False
                    for check_line in lines[i+1:i+10]:
                        if check_line.startswith('class ') or not check_line.startswith(' '):
                            if check_line.strip() != '' and not check_line.startswith(' '):
                                break
                        if 'model_config' in check_line:
                            has_config = True
                            break
                    
                    if not has_config:
                        # Insert model_config after the class definition (or docstring)
                        # We'll insert it right after the class declaration for simplicity, 
                        # but we need to respect indentation.
                        # Wait, a docstring might be right after. Let's just insert it here.
                        new_lines.append(f"    model_config = ConfigDict(extra='forbid')")
                        print(f"Added to {schema_name} in {file}")

            with open(path, 'w') as f:
                f.write('\n'.join(new_lines))
