"""Fix jockey analysis key mapping in backend viewlogic_analysis.py"""

path = "/opt/dlogic/backend/api/v2/viewlogic_analysis.py"
with open(path, "r") as f:
    content = f.read()

old = '''        for i, jname in enumerate(jockeys):
            if not jname:
                continue
            post = posts[i] if i < len(posts) else 0
            if post <= 6:
                post_zone = "内枠(1-6)"
            elif post <= 12:
                post_zone = "中枠(7-12)"
            else:
                post_zone = "外枠(13-18)"

            stats = jockey_post.get(jname, {})
            zone_stats = stats.get(post_zone, {})
            jockey_stats[jname] = {
                "horse": request.horses[i] if i < len(request.horses) else "",
                "horse_number": request.horse_numbers[i] if i < len(request.horse_numbers) else 0,
                "post_zone": post_zone,
                "fukusho_rate": round(zone_stats.get("fukusho_rate", 0) * 100, 1),
                "race_count": zone_stats.get("race_count", 0),
            }'''

new = '''        for i, jname in enumerate(jockeys):
            if not jname:
                continue
            post = posts[i] if i < len(posts) else 0
            if post <= 6:
                post_zone = "\u5185\u67a0\uff081-6\uff09"
            elif post <= 12:
                post_zone = "\u4e2d\u67a0\uff087-12\uff09"
            else:
                post_zone = "\u5916\u67a0\uff0813-18\uff09"

            stats = jockey_post.get(jname, {})
            # Engine returns nested: {assigned_post_stats: {fukusho_rate, race_count}, all_post_stats: {...}}
            assigned = stats.get("assigned_post_stats", {})
            all_posts = stats.get("all_post_stats", {})
            zone_stats = all_posts.get(post_zone, assigned)
            jockey_stats[jname] = {
                "horse": request.horses[i] if i < len(request.horses) else "",
                "horse_number": request.horse_numbers[i] if i < len(request.horse_numbers) else 0,
                "post_zone": post_zone,
                "fukusho_rate": round(zone_stats.get("fukusho_rate", 0), 1),
                "race_count": zone_stats.get("race_count", 0),
            }'''

if old in content:
    content = content.replace(old, new)
    with open(path, "w") as f:
        f.write(content)
    print("FIXED")
else:
    print("Pattern not found")
