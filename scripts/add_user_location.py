"""Add /api/user location block to nginx config."""

with open("/etc/nginx/sites-enabled/dlogic") as f:
    lines = f.readlines()

insert_block = [
    "\n",
    "    location /api/user {\n",
    "        proxy_pass http://127.0.0.1:5000;\n",
    "        proxy_set_header Host $host;\n",
    "        proxy_set_header X-Real-IP $remote_addr;\n",
    "        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;\n",
    "        proxy_set_header X-Forwarded-Proto $scheme;\n",
    "        proxy_read_timeout 30s;\n",
    "    }\n",
]

new_lines = []
for line in lines:
    if "location /api/chatauth" in line:
        new_lines.extend(insert_block)
    new_lines.append(line)

with open("/etc/nginx/sites-enabled/dlogic", "w") as f:
    f.writelines(new_lines)
print("OK")
