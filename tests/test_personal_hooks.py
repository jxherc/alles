import unittest

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from core.database import Base
from services import personal_index as pix


class PersonalHookTests(unittest.TestCase):
    def setUp(self):
        self.eng = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.eng)
        self.db = sessionmaker(bind=self.eng)()

    def tearDown(self):
        self.db.close()
        self.eng.dispose()

    def test_note_route_hooks(self):
        import routes.notes as routes

        created = routes.create_note(
            routes.NoteBody(title="ski trip", content="booked the cabin"), db=self.db
        )
        note_id = created["id"]
        self.assertTrue(pix.search(self.db, "cabin booked", kinds=["note"], k=5))
        routes.update_note(
            note_id,
            routes.NoteBody(title="ski trip", content="cancelled the cabin"),
            db=self.db,
        )
        self.assertTrue(pix.search(self.db, "cancelled", kinds=["note"], k=5))
        routes.delete_note(note_id, db=self.db)
        self.assertFalse(pix.search(self.db, "ski trip", kinds=["note"], k=5))


if __name__ == "__main__":
    unittest.main()
