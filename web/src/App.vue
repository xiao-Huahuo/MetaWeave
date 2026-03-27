<script setup>
import { computed } from 'vue'
import { useRoute } from 'vue-router'
import Header from './components/app/Header.vue'
import Sidebar from './components/app/Sidebar.vue'

const route = useRoute()
const isAuthPage = computed(() => ['/login', '/register'].includes(route.path))
</script>

<template>
  <div id="app">
    <Header v-if="!isAuthPage" />
    <div class="main">
      <Sidebar v-if="!isAuthPage" />
      <div class="content" :class="{ full: isAuthPage }">
        <router-view />
      </div>
    </div>
  </div>
</template>

<style>
#app {
  font-family: Avenir, Helvetica, Arial, sans-serif;
  -webkit-font-smoothing: antialiased;
  -moz-osx-font-smoothing: grayscale;
  color: #2c3e50;
}

.main {
  display: flex;
}

.content {
  flex: 1;
  padding: 20px;
}

.content.full {
  padding: 0;
}
</style>
