from core.database import Session
from tests._client import ApiTest


class ProjectsApiTest(ApiTest):
    def test_list_empty(self):
        self.assertEqual(self.client.get("/api/projects").json(), [])

    def test_project_files(self):
        pid = self.client.post("/api/projects", json={"name": "p"}).json()["id"]
        # no working dir → empty list, not a crash
        r = self.client.get(f"/api/projects/{pid}/files")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json(), {"files": [], "working_dir": ""})
        self.assertEqual(self.client.get("/api/projects/nope/files").status_code, 404)

    def test_create_patch_delete(self):
        p = self.client.post("/api/projects", json={"name": "proj", "color": "#abc"}).json()
        self.assertEqual(p["name"], "proj")
        self.assertEqual(p["session_count"], 0)
        pid = p["id"]

        r = self.client.patch(f"/api/projects/{pid}", json={"description": "d", "name": "renamed"})
        self.assertEqual(r.json()["name"], "renamed")
        self.assertEqual(r.json()["description"], "d")

        self.assertEqual(self.client.delete(f"/api/projects/{pid}").json(), {"ok": True})
        self.assertEqual(self.client.get("/api/projects").json(), [])

    def test_missing_404(self):
        self.assertEqual(
            self.client.patch("/api/projects/nope", json={"name": "x"}).status_code, 404
        )
        self.assertEqual(self.client.delete("/api/projects/nope").status_code, 404)

    def test_assign_unassign_session(self):
        pid = self.client.post("/api/projects", json={"name": "p"}).json()["id"]
        d = self.db()
        s = Session(name="chat")
        d.add(s)
        d.commit()
        sid = s.id
        d.close()

        self.assertEqual(
            self.client.post(f"/api/projects/{pid}/sessions/{sid}").json(), {"ok": True}
        )
        self.assertEqual(self.client.get("/api/projects").json()[0]["session_count"], 1)

        self.assertEqual(
            self.client.delete(f"/api/projects/{pid}/sessions/{sid}").json(), {"ok": True}
        )
        self.assertEqual(self.client.get("/api/projects").json()[0]["session_count"], 0)

    def test_delete_orphans_sessions_not_deletes_them(self):
        pid = self.client.post("/api/projects", json={"name": "p"}).json()["id"]
        d = self.db()
        s = Session(name="chat", project_id=pid)
        d.add(s)
        d.commit()
        sid = s.id
        d.close()
        self.client.delete(f"/api/projects/{pid}")
        d = self.db()
        s = d.get(Session, sid)
        self.assertIsNotNone(s)  # session survives
        self.assertIsNone(s.project_id)  # just unlinked
        d.close()

    def test_create_returns_all_fields(self):
        p = self.client.post(
            "/api/projects",
            json={"name": "full", "description": "desc", "system_prompt": "sp", "color": "#ff0"},
        ).json()
        self.assertEqual(p["name"], "full")
        self.assertEqual(p["description"], "desc")
        self.assertEqual(p["system_prompt"], "sp")
        self.assertEqual(p["color"], "#ff0")
        self.assertIn("id", p)
        self.assertIn("created_at", p)

    def test_patch_system_prompt_and_color(self):
        pid = self.client.post("/api/projects", json={"name": "p"}).json()["id"]
        d = self.client.patch(
            f"/api/projects/{pid}", json={"system_prompt": "be terse", "color": "#123"}
        ).json()
        self.assertEqual(d["system_prompt"], "be terse")
        self.assertEqual(d["color"], "#123")

    def test_unassign_session_not_in_project_is_noop(self):
        # unassigning a session that belongs to a different project → ok, session untouched
        pid1 = self.client.post("/api/projects", json={"name": "a"}).json()["id"]
        pid2 = self.client.post("/api/projects", json={"name": "b"}).json()["id"]
        d = self.db()
        s = Session(name="chat", project_id=pid1)
        d.add(s)
        d.commit()
        sid = s.id
        d.close()
        # try to unassign from pid2 — session belongs to pid1
        r = self.client.delete(f"/api/projects/{pid2}/sessions/{sid}")
        self.assertEqual(r.json(), {"ok": True})
        d = self.db()
        s = d.get(Session, sid)
        self.assertEqual(s.project_id, pid1)  # still linked to pid1
        d.close()

    def test_multiple_projects_list_order(self):
        self.client.post("/api/projects", json={"name": "alpha"})
        self.client.post("/api/projects", json={"name": "beta"})
        lst = self.client.get("/api/projects").json()
        self.assertEqual(len(lst), 2)
        self.assertEqual(lst[0]["name"], "alpha")
        self.assertEqual(lst[1]["name"], "beta")
