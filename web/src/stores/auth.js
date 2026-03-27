import { defineStore } from 'pinia';
import { ref, computed } from 'vue';
import { apiClient, API_ROUTES } from '../router/api_routes';

export const useAuthStore = defineStore('auth', () => {
  const token = ref(localStorage.getItem('token') || '');
  const user = ref(JSON.parse(localStorage.getItem('user') || '{}'));
  const isAuthenticated = computed(() => !!token.value);
  const isAdmin = computed(() => user.value.is_admin);

  const setToken = (newToken) => {
    token.value = newToken;
    localStorage.setItem('token', newToken);
  };

  const fetchUser = async () => {
    if (token.value) {
      try {
        const response = await apiClient.get(API_ROUTES.GET_ME);
        user.value = response.data;
        localStorage.setItem('user', JSON.stringify(user.value));
      } catch (error) {
        console.error('Failed to fetch user:', error);
        token.value = '';
        user.value = {};
        localStorage.removeItem('token');
        localStorage.removeItem('user');
      }
    }
  };

  const login = async (credentials) => {
    try {
      const params = new URLSearchParams();
      params.append('username', credentials.uname || '');
      params.append('password', credentials.password || '');

      const response = await apiClient.post(API_ROUTES.LOGIN, params, {
        headers: {
          'Content-Type': 'application/x-www-form-urlencoded',
        },
      });
      setToken(response.data.access_token);
      await fetchUser();
      return { success: true };
    } catch (error) {
      return { success: false, error: error.response?.data?.detail || 'Login failed' };
    }
  };

  const register = async (userData) => {
    try {
      const response = await apiClient.post(API_ROUTES.REGISTER, userData);
      return { success: true, message: 'Registration successful' };
    } catch (error) {
      return { success: false, error: error.response?.data?.detail || 'Registration failed' };
    }
  };

  const logout = () => {
    token.value = '';
    user.value = {};
    localStorage.removeItem('token');
    localStorage.removeItem('user');
  };

  return { token, user, isAuthenticated, isAdmin, login, register, logout, fetchUser };
});
