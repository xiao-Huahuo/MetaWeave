import axios from 'axios';

// API 路径常量
export const API_ROUTES = {
  LOGIN: '/login/',
  REGISTER: '/user',
  GET_ME: '/user/me',
  UPDATE_ME: '/user/me',
  ADMIN_USERS: '/admin/users',
  ADMIN_USER: (uid) => `/admin/users/${uid}`,
};

// 统一API Client
export const apiClient = axios.create({
  baseURL: '/api',
  headers: { 'Content-Type': 'application/json' },
  timeout: 60000, // request timeout
});

// 请求拦截器：自动附加 Token
apiClient.interceptors.request.use(config => {
  const token = localStorage.getItem('token');
  if (token) config.headers.Authorization = `Bearer ${token}`;
  return config;
}, error => Promise.reject(error));


