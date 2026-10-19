from app.services.image_host import R2ImageHost


class FakeS3:
    def __init__(self):
        self.calls = []

    def put_object(self, **kwargs):
        self.calls.append(("put", kwargs))

    def delete_object(self, **kwargs):
        self.calls.append(("delete", kwargs))


def test_upload_returns_public_url_and_delete_removes_object():
    s3 = FakeS3()
    host = R2ImageHost(s3, "bucket", "https://pub.example/")

    url = host.upload("instagram/a.jpg", b"jpeg")
    host.delete("instagram/a.jpg")

    assert url == "https://pub.example/instagram/a.jpg"
    assert s3.calls == [
        ("put", {"Bucket": "bucket", "Key": "instagram/a.jpg", "Body": b"jpeg", "ContentType": "image/jpeg"}),
        ("delete", {"Bucket": "bucket", "Key": "instagram/a.jpg"}),
    ]
