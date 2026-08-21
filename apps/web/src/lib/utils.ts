import { type ClassValue, clsx } from "clsx";
import { twMerge } from "tailwind-merge";

/** clsx alone is not enough: Tailwind classes CONFLICT (`p-2 p-4`), and last-wins depends
 *  on stylesheet order, not argument order. twMerge resolves conflicts by intent. */
export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}
