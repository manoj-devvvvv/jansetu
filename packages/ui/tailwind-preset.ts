import type { Config } from "tailwindcss";
import { colors } from "./src/tokens/colors";

const config = {
  theme: {
    extend: {
      colors: {
        primary: {
          DEFAULT: colors.primary,
          dark: colors.primaryDark,
        },
        secondary: colors.secondary,
        success: colors.success,
        error: colors.error,
        background: colors.background,
        surface: colors.surface,
        text: {
          DEFAULT: colors.text,
          secondary: colors.textSecondary,
        },
        border: colors.border,
      },
    },
  },
} satisfies Partial<Config>;

export default config;
