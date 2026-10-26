"""The Agent Skill must follow the Agent Skills format (https://agentskills.io)."""

import re
import unittest
from pathlib import Path

SKILLS = Path(__file__).resolve().parent.parent / "skills"


def frontmatter(path):
    text = path.read_text(encoding="utf-8")
    match = re.match(r"^---\n(.*?)\n---\n", text, re.DOTALL)
    assert match, f"{path} has no frontmatter"
    fields = {}
    for line in match.group(1).splitlines():
        key, _, value = line.partition(":")
        fields[key.strip()] = value.strip()
    return fields, text[match.end():]


class SkillFormatTest(unittest.TestCase):
    def test_every_skill(self):
        skills = sorted(SKILLS.glob("*/SKILL.md"))
        self.assertTrue(skills)
        for path in skills:
            with self.subTest(skill=path.parent.name):
                fields, body = frontmatter(path)
                self.assertEqual(fields["name"], path.parent.name)
                self.assertRegex(fields["name"], r"^[a-z0-9]+(-[a-z0-9]+)*$")
                self.assertLessEqual(len(fields["name"]), 64)
                self.assertTrue(fields["description"])
                self.assertLessEqual(len(fields["description"]), 1024)
                self.assertLessEqual(len(fields.get("compatibility", "")), 500)
                self.assertTrue(body.strip())

    def test_commands_in_the_skill_exist(self):
        from ofdkit.cli import build_parser

        commands = set(build_parser()._subparsers._group_actions[0].choices)
        _, body = frontmatter(SKILLS / "ofd-reader" / "SKILL.md")
        used = set(re.findall(r"uvx ofdkit (\w+)", body))
        self.assertTrue(used)
        self.assertLessEqual(used, commands)


if __name__ == "__main__":
    unittest.main()
