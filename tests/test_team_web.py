import io
import os
import tempfile
import unittest
from subprocess import CompletedProcess
from unittest import mock


class TeamWebTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        os.environ["SAU_TEAM_DATA_DIR"] = cls.temp.name
        os.environ["SAU_ADMIN_PASSWORD"] = "TestPassword!123"
        os.environ["SAU_SECRET_KEY"] = "test-secret"
        import team_web
        cls.module = team_web

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def setUp(self):
        self.client = self.module.app.test_client()

    def login(self):
        response = self.client.post("/api/auth/login", json={"username": "admin", "password": "TestPassword!123"})
        self.assertEqual(response.status_code, 200)
        return response.get_json()["csrf"]

    def test_auth_and_csrf(self):
        self.assertEqual(self.client.get("/api/dashboard").status_code, 401)
        csrf = self.login()
        self.assertEqual(self.client.get("/api/dashboard").status_code, 200)
        self.assertEqual(self.client.post("/api/users", json={}).status_code, 403)
        self.assertTrue(csrf)

    def test_complete_publish_job_lifecycle(self):
        csrf = self.login()
        headers = {"X-CSRF-Token": csrf}
        account = self.client.post("/api/accounts", headers=headers, json={"platform": "douyin", "display_name": "验收账号"})
        self.assertEqual(account.status_code, 201)
        account_id = account.get_json()["id"]
        material = self.client.post(
            "/api/materials",
            headers=headers,
            data={"file": (io.BytesIO(b"test-video-content"), "acceptance.mp4")},
            content_type="multipart/form-data",
        )
        self.assertEqual(material.status_code, 201)

        invalid = self.client.post("/api/jobs", headers=headers, json={"material_id": material.get_json()["id"], "title": "验收", "account_ids": [account_id]})
        self.assertEqual(invalid.status_code, 400)
        with self.module.db() as conn:
            conn.execute("UPDATE platform_accounts SET status='ready' WHERE id=?", (account_id,))
        with mock.patch.object(self.module.job_queue, "put") as enqueue:
            created = self.client.post("/api/jobs", headers=headers, json={
                "material_id": material.get_json()["id"], "title": "完整流程验收",
                "description": "自动化测试", "tags": "测试", "platforms": ["douyin"],
                "account_ids": [account_id], "owner_user_id": 1,
            })
        self.assertEqual(created.status_code, 201)
        enqueue.assert_called_once_with(created.get_json()["id"])

        with mock.patch.object(self.module.subprocess, "run", return_value=CompletedProcess([], 0, "published", "")):
            self.module.run_job(created.get_json()["id"])
        job = next(item for item in self.client.get("/api/jobs").get_json() if item["id"] == created.get_json()["id"])
        self.assertEqual(job["status"], "success")
        self.assertEqual(job["targets"][0]["status"], "success")

    def test_management_lifecycle_and_retry(self):
        csrf = self.login(); headers = {"X-CSRF-Token": csrf}
        upload = self.client.post("/api/materials", headers=headers, data={"file": (io.BytesIO(b"temporary"), "temporary.mp4")}, content_type="multipart/form-data")
        material_id = upload.get_json()["id"]
        self.assertEqual(self.client.patch(f"/api/materials/{material_id}", headers=headers, json={"name": "已重命名.mp4"}).status_code, 200)
        self.assertEqual(self.client.delete(f"/api/materials/{material_id}", headers=headers).status_code, 200)

        account = self.client.post("/api/accounts", headers=headers, json={"platform": "kuaishou", "display_name": "临时账号"})
        account_id = account.get_json()["id"]
        self.assertEqual(self.client.get(f"/api/accounts/{account_id}/access").get_json(), {"user_ids": []})
        self.assertEqual(self.client.delete(f"/api/accounts/{account_id}", headers=headers).status_code, 200)

        published_material = self.client.post("/api/materials", headers=headers, data={"file": (io.BytesIO(b"publish"), "retry.mp4")}, content_type="multipart/form-data").get_json()["id"]
        published_account = self.client.post("/api/accounts", headers=headers, json={"platform": "douyin", "display_name": "重试账号"}).get_json()["id"]
        with self.module.db() as conn:
            conn.execute("UPDATE platform_accounts SET status='ready' WHERE id=?", (published_account,))
        with mock.patch.object(self.module.job_queue, "put"):
            job_id = self.client.post("/api/jobs", headers=headers, json={"material_id": published_material, "title": "重试测试", "platforms": ["douyin"], "account_ids": [published_account], "owner_user_id": 1}).get_json()["id"]
        with self.module.db() as conn:
            conn.execute("UPDATE jobs SET status='partial_failed' WHERE id=?", (job_id,))
            conn.execute("UPDATE job_targets SET status='failed',output='test error' WHERE job_id=?", (job_id,))
        with mock.patch.object(self.module.job_queue, "put") as enqueue:
            retry = self.client.post(f"/api/jobs/{job_id}/retry", headers=headers)
        self.assertEqual(retry.status_code, 200)
        enqueue.assert_called_once_with(job_id)
        self.assertEqual(self.client.delete(f"/api/materials/{published_material}", headers=headers).status_code, 409)
        self.assertEqual(self.client.delete(f"/api/accounts/{published_account}", headers=headers).status_code, 409)

    def test_admin_workflow(self):
        csrf = self.login()
        headers = {"X-CSRF-Token": csrf}
        user = self.client.post("/api/users", headers=headers, json={"username": "editor", "display_name": "编辑", "password": "EditorPass!123", "role": "operator"})
        self.assertEqual(user.status_code, 201)
        account = self.client.post("/api/accounts", headers=headers, json={"platform": "douyin", "display_name": "品牌主号"})
        self.assertEqual(account.status_code, 201)
        self.assertTrue(account.get_json()["account_name"].startswith("account_"))
        grant = self.client.put(f"/api/accounts/{account.get_json()['id']}/access", headers=headers, json={"user_ids": [user.get_json()["id"]]})
        self.assertEqual(grant.status_code, 200)
        upload = self.client.post("/api/materials", headers=headers, data={"file": (io.BytesIO(b"fake-video"), "demo.mp4")}, content_type="multipart/form-data")
        self.assertEqual(upload.status_code, 201)
        self.assertEqual(len(self.client.get("/api/materials").get_json()), 1)

    def test_central_account_owner_and_publish_guard(self):
        csrf = self.login(); headers = {"X-CSRF-Token": csrf}
        alice = self.client.post("/api/users", headers=headers, json={"username": "alice", "display_name": "小王", "password": "AlicePass!123", "role": "operator"}).get_json()["id"]
        bob = self.client.post("/api/users", headers=headers, json={"username": "bob", "display_name": "小李", "password": "BobPass!1234", "role": "operator"}).get_json()["id"]
        account = self.client.post("/api/accounts", headers=headers, json={"platform": "douyin", "display_name": "小王抖音号", "owner_user_id": alice})
        self.assertEqual(account.status_code, 201)
        account_id = account.get_json()["id"]
        with self.module.db() as conn:
            conn.execute("UPDATE platform_accounts SET status='ready' WHERE id=?", (account_id,))
        listed = next(x for x in self.client.get("/api/accounts").get_json() if x["id"] == account_id)
        self.assertEqual(listed["owner_user_id"], alice)
        self.assertEqual(listed["owner_display_name"], "小王")
        material_id = self.client.post("/api/materials", headers=headers, data={"file": (io.BytesIO(b"owner-test"), "owner.mp4")}, content_type="multipart/form-data").get_json()["id"]
        wrong = self.client.post("/api/jobs", headers=headers, json={"material_id": material_id, "title": "错误归属", "platforms": ["douyin"], "account_ids": [account_id], "owner_user_id": bob})
        self.assertEqual(wrong.status_code, 400)
        with mock.patch.object(self.module.job_queue, "put") as enqueue:
            correct = self.client.post("/api/jobs", headers=headers, json={"material_id": material_id, "title": "集中发布", "platforms": ["douyin"], "account_ids": [account_id], "owner_user_id": alice})
        self.assertEqual(correct.status_code, 201)
        enqueue.assert_called_once_with(correct.get_json()["id"])


if __name__ == "__main__":
    unittest.main()
