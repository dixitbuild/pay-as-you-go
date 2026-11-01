from rest_framework.test import APITestCase


class AuthTests(APITestCase):
    def test_register_and_login(self):
        r = self.client.post("/auth/register/", {"username": "u1", "password": "pass12345!x", "role": "USER"})
        self.assertEqual(r.status_code, 201)
        self.assertIn("token", r.data)
        r = self.client.post("/auth/login/", {"username": "u1", "password": "pass12345!x"})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.data["role"], "USER")

    def test_bad_login_returns_400(self):
        r = self.client.post("/auth/login/", {"username": "nope", "password": "x"})
        self.assertEqual(r.status_code, 400)

    def test_register_provider_role(self):
        r = self.client.post("/auth/register/", {"username": "p1", "password": "pass12345!x", "role": "PROVIDER"})
        self.assertEqual(r.data["role"], "PROVIDER")
