import { createRouter, createWebHistory } from 'vue-router'
import Home from '../views/Home.vue'
import DiscoveryHome from '../views/DiscoveryHome.vue'
import LoginOrRegister from '../views/LoginOrRegister.vue'
import Admin from '../views/Admin.vue'

const router = createRouter({
  history: createWebHistory(import.meta.env.BASE_URL),
  routes: [
    { path: '/', name: 'home', component: Home, meta: { requiresAuth: true } },
    { path: '/discovery-home', name: 'discovery-home', component: DiscoveryHome, meta: { requiresAuth: true } },
    {
      path: '/login',
      name: 'login',
      component: LoginOrRegister,
      props: { defaultMode: 'login' },
      meta: { guest: true },
    },
    {
      path: '/register',
      name: 'register',
      component: LoginOrRegister,
      props: { defaultMode: 'register' },
      meta: { guest: true },
    },
    { path: '/admin', name: 'admin', component: Admin, meta: { requiresAuth: true, requiresAdmin: true } },
  ],
})

// 路由守卫
router.beforeEach(async (to, from, next) => {
  const token = localStorage.getItem('token')
  const isAuthenticated = !!token
  const user = JSON.parse(localStorage.getItem('user') || '{}')
  const isAdmin = user.is_admin

  if (to.meta.requiresAuth && !isAuthenticated) {
    next('/login')
  } else if (to.meta.guest && isAuthenticated) {
    next('/')
  } else if (to.meta.requiresAdmin && !isAdmin) {
    next('/login')
  } else {
    next()
  }
})

export default router
