"use client";

import * as React from "react";
import { Command as CommandPrimitive } from "cmdk";
import { cn } from "./utils";

/**
 * shadcn `command` (cmdk), upgraded to the game's list vocabulary: the
 * selected row is the white-glow selection recipe over the hover wash
 * (`--effect-selected-glow` / `--accent`), rows ride the text ramp, square
 * corners, serif chrome. No stock palette, no rounded corners.
 */
function Command({
  className,
  ...props
}: React.ComponentProps<typeof CommandPrimitive>) {
  return (
    <CommandPrimitive
      data-slot="command"
      className={cn(
        "flex h-full w-full flex-col overflow-hidden bg-popover font-ui text-popover-foreground",
        className,
      )}
      {...props}
    />
  );
}

function CommandInput({
  className,
  ...props
}: React.ComponentProps<typeof CommandPrimitive.Input>) {
  return (
    <div
      data-slot="command-input-wrapper"
      className="flex items-center border-b border-input px-g5"
    >
      <CommandPrimitive.Input
        data-slot="command-input"
        className={cn(
          "h-[35px] w-full bg-transparent py-g4 font-ui text-base text-text-emph",
          "placeholder:text-text-disabled outline-none",
          "disabled:cursor-not-allowed disabled:[filter:var(--effect-disabled)]",
          className,
        )}
        {...props}
      />
    </div>
  );
}

function CommandList({
  className,
  ...props
}: React.ComponentProps<typeof CommandPrimitive.List>) {
  return (
    <CommandPrimitive.List
      data-slot="command-list"
      className={cn(
        "max-h-[300px] scroll-py-g3 overflow-y-auto overflow-x-hidden",
        className,
      )}
      {...props}
    />
  );
}

function CommandEmpty(
  props: React.ComponentProps<typeof CommandPrimitive.Empty>,
) {
  return (
    <CommandPrimitive.Empty
      data-slot="command-empty"
      className="py-g6 text-center text-base text-text-desc"
      {...props}
    />
  );
}

function CommandGroup({
  className,
  ...props
}: React.ComponentProps<typeof CommandPrimitive.Group>) {
  return (
    <CommandPrimitive.Group
      data-slot="command-group"
      className={cn("overflow-hidden p-g2 text-foreground", className)}
      {...props}
    />
  );
}

function CommandItem({
  className,
  ...props
}: React.ComponentProps<typeof CommandPrimitive.Item>) {
  return (
    <CommandPrimitive.Item
      data-slot="command-item"
      className={cn(
        "relative flex cursor-pointer items-center gap-g3 px-g5 py-g4 outline-none",
        "text-text-main transition-[color,background-color,box-shadow] duration-[var(--duration-fast)] ease-[var(--ease-state)]",
        "data-[selected=true]:bg-accent data-[selected=true]:text-accent-foreground",
        "data-[selected=true]:[box-shadow:var(--effect-selected-glow)]",
        "data-[disabled=true]:pointer-events-none data-[disabled=true]:text-text-disabled data-[disabled=true]:[filter:var(--effect-disabled)]",
        className,
      )}
      {...props}
    />
  );
}

export { Command, CommandInput, CommandList, CommandEmpty, CommandGroup, CommandItem };
