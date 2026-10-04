<!-- Completion marks persisted onboarding complete only after the explicit entry button succeeds. -->
<script setup lang="ts">
defineProps<{ active: boolean; busy?: boolean }>()
defineEmits<{ enter: [] }>()
</script>
<template>
  <section class="auth-step auth-completion">
    <div v-if="active" class="auth-fireworks" aria-hidden="true">
      <i
        v-for="n in 20"
        :key="n"
        :style="{ '--angle': n * 18 + 'deg', '--delay': (n % 4) * 0.08 + 's' }"
      />
    </div>
    <h1>完成</h1>
    <button class="auth-button" type="button" :disabled="busy" @click="$emit('enter')">进入主页</button>
  </section>
</template>
