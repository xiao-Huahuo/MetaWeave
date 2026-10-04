<!-- Shared capsule field using the supplied blue-form geometry and application theme. -->
<script setup lang="ts">
import { computed, ref, useId } from 'vue'
import IcIcon from '@/components/common/IcIcon.vue'
const value = defineModel<string>({ required: true })
const props = withDefaults(
  defineProps<{
    label: string
    type?: string
    placeholder?: string
    autocomplete?: string
    required?: boolean
    readonly?: boolean
  }>(),
  { type: 'text', placeholder: '', autocomplete: 'off', required: false },
)
const id = useId()
const revealed = ref(false)
const inputType = computed(() =>
  props.type === 'password' && revealed.value ? 'text' : props.type,
)
</script>
<template>
  <div class="auth-field">
    <label :for="id">{{ label }}</label>
    <div class="auth-input-box">
      <input
        :id="id"
        v-model="value"
        :type="inputType"
        :placeholder="placeholder"
        :autocomplete="autocomplete"
        :required="required"
        :readonly="readonly"
        :spellcheck="false"
      />
      <button
        v-if="type === 'password'"
        class="auth-reveal"
        type="button"
        :aria-label="revealed ? '隐藏' + label : '显示' + label"
        :aria-pressed="revealed"
        @click="revealed = !revealed"
      >
        <IcIcon :name="revealed ? 'visibility-off' : 'visibility'" :size="18" />
      </button>
    </div>
  </div>
</template>
