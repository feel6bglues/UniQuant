import pandas as pd

from uniquant.data.utils.akshare_reference_service import AkshareReferenceService


def test_akshare_reference_service_routes_global_news_source():
    calls = []
    service = AkshareReferenceService(
        lambda method_name, **kwargs: calls.append(method_name) or pd.DataFrame({"x": [1]})
    )

    result = service.fetch_global_news("ths")

    assert not result.empty
    assert calls == ["stock_info_global_ths"]


def test_akshare_reference_service_fetches_industry_list():
    service = AkshareReferenceService(
        lambda method_name, **kwargs: pd.DataFrame({"name": ["银行"]})
        if method_name == "stock_board_industry_name_em"
        else pd.DataFrame()
    )

    result = service.fetch_industry_list()

    assert result.iloc[0]["name"] == "银行"
