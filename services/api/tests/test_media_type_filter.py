"""Execute the actual classification predicate and pagination against SQLite."""
import unittest
from sqlalchemy import Column, MetaData, String, Table, create_engine, func, select
from app.media_filter import image_asset_condition


class MediaTypeFilterTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite://")
        metadata = MetaData()
        self.media = Table("media_assets", metadata, *[
            Column(name, String, primary_key=name == "id")
            for name in ("id", "filename", "original_path", "source_path")])
        self.catalog = Table("curator_catalog_assets", metadata, *[
            Column(name, String, primary_key=name == "asset_id")
            for name in ("asset_id", "media_id", "asset_type")])
        metadata.create_all(self.engine)
        self.db = self.engine.connect()
        fixtures = [
            ("1", "extensionless image", None, None),
            ("2", "Photo.JPG", None, None),
            ("3", "renamed", "/share/photo.TIFF", None),
            ("4", "video", "/share/clip.mp4", None),
            ("5", "unknown", None, None),
            ("6", "misleading.jpg", None, None),
            ("7", "original", None, "/source/scan.PNG"),
        ]
        self.db.execute(self.media.insert(), [
            dict(zip(("id", "filename", "original_path", "source_path"), row)) for row in fixtures])
        self.db.execute(self.catalog.insert(), [
            {"asset_id": "a", "media_id": "1", "asset_type": "Image"},
            {"asset_id": "b", "media_id": "6", "asset_type": "Media"},
        ])
        self.image = image_asset_condition(self.media.c, self.catalog.c)

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def ids(self, condition):
        return list(self.db.execute(select(self.media.c.id).where(condition)
                                   .order_by(self.media.c.id)).scalars())

    def test_images_catalog_and_extensions(self):
        self.assertEqual(self.ids(self.image), ["1", "2", "3", "7"])

    def test_hide_images_preserves_unknown_and_explicit_video(self):
        self.assertEqual(self.ids(~self.image), ["4", "5", "6"])

    def test_filter_counts_before_pagination(self):
        for condition, expected in ((self.image, ["1", "2", "3", "7"]),
                                    (~self.image, ["4", "5", "6"])):
            query = select(self.media.c.id).where(condition).order_by(self.media.c.id)
            total = self.db.scalar(select(func.count()).select_from(query.subquery()))
            pages = [list(self.db.execute(query.limit(2).offset(offset)).scalars())
                     for offset in range(0, total, 2)]
            self.assertEqual(total, len(expected))
            self.assertEqual([item for page in pages for item in page], expected)