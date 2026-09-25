"""Library image classification without guessing from duration or thumbnails."""
from sqlalchemy import exists, or_, select

IMAGE_EXTENSIONS = ("jpg", "jpeg", "png", "gif", "webp", "bmp", "tif", "tiff", "heic", "heif", "avif", "svg", "exr", "dpx")


def image_asset_condition(MediaAsset, CatalogAsset):
    linked = exists(select(CatalogAsset.asset_id).where(CatalogAsset.media_id == MediaAsset.id))
    catalog_image = exists(select(CatalogAsset.asset_id).where(
        CatalogAsset.media_id == MediaAsset.id, CatalogAsset.asset_type == "Image"))
    # Curator's explicit type wins over proxy/container filename hints.
    extensions = or_(*[
        column.ilike("%." + ext)
        for column in (MediaAsset.filename, MediaAsset.original_path, MediaAsset.source_path)
        for ext in IMAGE_EXTENSIONS
    ])
    from sqlalchemy import func
    return catalog_image | (~linked & func.coalesce(extensions, False))