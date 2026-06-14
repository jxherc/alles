from tests._client import ApiTest
from core.database import Session


class ProjectsApiTest(ApiTest):
    def test_list_empty(self):
        self.assertEqual(self.client.get("/api/projects").json(), [])

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
        self.assertEqual(self.client.patch("/api/projects/nope", json={"name": "x"}).status_code, 404)
        self.assertEqual(self.client.delete("/api/projects/nope").status_code, 404)

    def test_assign_unassign_session(self):
        pid = self.client.post("/api/projects", json={"name": "p"}).json()["id"]
        d = self.db(); s = Session(name="chat"); d.add(s); d.commit(); sid = s.id; d.close()

        self.assertEqual(self.client.post(f"/api/projects/{pid}/sessions/{sid}").json(), {"ok": True})
        self.assertEqual(self.client.get("/api/projects").json()[0]["session_count"], 1)

        self.assertEqual(self.client.delete(f"/api/projects/{pid}/sessions/{sid}").json(), {"ok": True})
        self.assertEqual(self.client.get("/api/projects").json()[0]["session_count"], 0)

    def test_delete_orphans_sessions_not_deletes_them(self):
        pid = self.client.post("/api/projects", json={"name": "p"}).json()["id"]
        d = self.db(); s = Session(name="chat", project_id=pid); d.add(s); d.commit(); sid = s.id; d.close()
        self.client.delete(f"/api/projects/{pid}")
        d = self.db(); s = d.get(Session, sid)
        self.assertIsNotNone(s)             # session survives
        self.assertIsNone(s.project_id)     # just unlinked
        d.close()
