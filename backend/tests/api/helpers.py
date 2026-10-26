def assert_problem_details(response, *, status, code):
    assert response.status_code == status
    assert response["Content-Type"] == "application/problem+json"

    body = response.json()
    assert body["type"] == "about:blank"
    assert body["title"]
    assert body["status"] == status
    assert body["detail"]
    assert body["code"] == code
    return body
