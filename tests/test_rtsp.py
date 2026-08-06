import pytest

from pyfanvil.rtsp import RTSPStreamConfig, build_rtsp_url


def test_builds_operator_confirmed_stream_url_without_credentials():
    assert (
        build_rtsp_url(
            RTSPStreamConfig(host="192.0.2.10", path="/live/ch00_0"),
        )
        == "rtsp://192.0.2.10:554/live/ch00_0"
    )


def test_quotes_credentials_and_normalizes_custom_path():
    url = build_rtsp_url(
        RTSPStreamConfig(
            host="192.0.2.10",
            username="rtsp user",
            password="p@ss/word",
            port=8554,
            path="stream.live0",
        ),
    )

    assert url == "rtsp://rtsp%20user:p%40ss%2Fword@192.0.2.10:8554/stream.live0"


@pytest.mark.parametrize(
    ("config", "message"),
    [
        (RTSPStreamConfig(host=" ", path="/live"), "RTSP host is required"),
        (RTSPStreamConfig(host="camera", path=" "), "RTSP path is required"),
        (
            RTSPStreamConfig(host="camera", path="/live", port=0),
            "RTSP port must be between 1 and 65535",
        ),
    ],
)
def test_rejects_incomplete_or_invalid_config(config, message):
    with pytest.raises(ValueError, match=message):
        build_rtsp_url(config)
