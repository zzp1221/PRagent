import hashlib
import hmac
import unittest

from pragent.github import verify_signature
from agentic_fake import FakeGitHubComments


ISSUE_URL = "https://api.github.com/repos/org/repo/issues/7"
MARKER = "<!-- pragent-review:org/repo#7 -->"


class GitHubSignatureTests(unittest.TestCase):
    def test_signature_verification(self):
        body = b'{"ok":true}'
        signature = "sha256=" + hmac.new(b"secret", body, hashlib.sha256).hexdigest()
        self.assertTrue(verify_signature("secret", body, signature))
        self.assertFalse(verify_signature("wrong", body, signature))


class GitHubCommentTests(unittest.TestCase):
    def test_upsert_updates_the_same_marker_instead_of_posting_again(self):
        api = FakeGitHubComments()
        self.assertEqual("created", api.upsert_comment(ISSUE_URL, "first", MARKER))
        self.assertEqual("updated", api.upsert_comment(ISSUE_URL, "second", MARKER))
        self.assertEqual(1, len(api.comments))
        self.assertIn("second", api.comments[0]["body"])
        self.assertNotIn("first", api.comments[0]["body"])

    def test_upsert_finds_marker_on_a_later_page(self):
        api = FakeGitHubComments()
        for index in range(150):
            api.comments.append({
                "url": "https://api.github.com/comments/%d" % index,
                "body": "noise %d" % index,
            })
        api.comments[130]["body"] = MARKER + "\nolder review"
        self.assertEqual("updated", api.upsert_comment(ISSUE_URL, "fresh", MARKER))
        self.assertEqual(150, len(api.comments))
        self.assertIn("fresh", api.comments[130]["body"])

    def test_upsert_skips_a_marked_comment_it_cannot_edit(self):
        api = FakeGitHubComments()
        foreign = "https://api.github.com/comments/999"
        api.comments.append({"url": foreign, "body": MARKER + "\nforged by author"})
        api.readonly_urls.add(foreign)
        self.assertEqual("created", api.upsert_comment(ISSUE_URL, "ours", MARKER))
        self.assertEqual(2, len(api.comments))
        self.assertIn("ours", api.comments[1]["body"])
        self.assertIn("forged by author", api.comments[0]["body"])


if __name__ == "__main__":
    unittest.main()

