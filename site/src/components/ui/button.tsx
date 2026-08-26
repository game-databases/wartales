import * as React from "react";
import { cva, type VariantProps } from "class-variance-authority";
import { cn } from "./utils";

/**
 * shadcn `button`, upgraded to the game's own chrome (shadcn-adoption
 * §layers — never a stock look):
 *  - square surfaces (F1 §2.4 canon: a rounded corner is a defect);
 *  - hover = white outline + text brightens to the white voice
 *    (`--effect-hover-outline` / `--accent-foreground`, §2.5 recipe);
 *  - focus = the destiny gold highlight ring (`--effect-gold-highlight-ring`,
 *    `--ring` is gold and gold stays selection/focus-only);
 *  - disabled = the game's own disabled filter + disabled text token;
 *  - motion rides the canon duration/ease only; type rides --font-ui at the
 *    canon ramp (14/16px steps — ≥12px floor).
 */
const buttonVariants = cva(
  [
    "inline-flex items-center justify-center gap-g3 whitespace-nowrap font-ui text-base",
    "transition-[color,background-color,box-shadow] duration-[var(--duration-fast)] ease-[var(--ease-state)]",
    "focus-visible:[outline:none] focus-visible:[box-shadow:var(--effect-gold-highlight-ring)]",
    "disabled:pointer-events-none disabled:text-text-disabled disabled:[filter:var(--effect-disabled)]",
  ],
  {
    variants: {
      variant: {
        default:
          "border border-border bg-bg-4 text-text-bright hover:bg-accent hover:text-accent-foreground hover:[box-shadow:var(--effect-hover-outline)]",
        outline:
          "border border-border bg-transparent text-text-main hover:text-accent-foreground hover:[box-shadow:var(--effect-hover-outline)]",
        ghost:
          "border border-transparent bg-transparent text-text-main hover:bg-accent hover:text-accent-foreground hover:[box-shadow:var(--effect-hover-outline)]",
      },
      size: {
        sm: "h-[28px] px-g5",
        default: "h-[35px] px-g6", // the HeaderBg band's own height step
        lg: "h-[45px] px-g7",
        icon: "h-[35px] w-[35px]",
      },
    },
    defaultVariants: {
      variant: "default",
      size: "default",
    },
  },
);

function Button({
  className,
  variant,
  size,
  ...props
}: React.ComponentProps<"button"> & VariantProps<typeof buttonVariants>) {
  return (
    <button
      data-slot="button"
      className={cn(buttonVariants({ variant, size }), className)}
      {...props}
    />
  );
}

export { Button, buttonVariants };
