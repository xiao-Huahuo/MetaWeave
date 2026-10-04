<!-- Onboarding toggle matches the existing basic-settings switch dimensions and states. -->
<script setup lang="ts">
import { useId } from 'vue'
const value = defineModel<boolean>({ required: true })
defineProps<{ label: string; disabled?: boolean }>()
const id = useId()
</script>
<template>
  <div class="auth-toggle" :class="{ disabled }">
    <label :for="id">{{ label }}</label
    ><input :id="id" v-model="value" type="checkbox" :disabled="disabled" />
  </div>
</template>
